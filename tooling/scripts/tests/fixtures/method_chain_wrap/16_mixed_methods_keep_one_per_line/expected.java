public class Demo
{
    public Result run()
    {
        return Builder.newInstance().withFirstName("Alice")
                                    .withSecondName("Smith")
                                    .withThirdName("Jr")
                                    .build();
    }
}
