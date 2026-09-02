public class T
{
    boolean equals(Object obj)
    {
        if (obj == null || this.getClass() != obj.getClass()) return false;
        return true;
    }
}
