public class Foo
{
    public void method()
    {
        while (this.availableConnections.size()
                < this.allConnections.size())
        {
            doSomething();
        }
    }
}
